"""Tests for Phase 8 Task 8.2: Ledger Lineage Explorer & Bi-Directional Provenance DAG."""

import sqlite3
import pytest

from ironledger.db import migrations
from ironledger.db.connection import connect
from ironledger.lineage.models import (
    LineageNode,
    LineageEdge,
    LineageError,
    LineageNodeNotFoundError,
    LineageCycleError,
)
from ironledger.lineage.dag import LineageDAG
from ironledger.lineage.explorer import LineageExplorer


@pytest.fixture
def db_conn():
    conn = connect(":memory:")
    migrations.migrate(conn)
    return conn


# ============================================================================
# 1. Node & Edge CRUD, Constraints, and Self-Edge Rejection
# ============================================================================


def test_create_lineage_nodes_and_edges(db_conn):
    dag = LineageDAG(db_conn)

    evidence_node = LineageNode(
        node_id="ev_001",
        node_type="EVIDENCE_BLOB",
        entity_ref="evidence/raw/bank_statement.pdf",
        metadata={"sha256": "abcdef1234567890" * 4},
        ledger_id="default",
    )
    record_node = LineageNode(
        node_id="rec_001",
        node_type="SOURCE_RECORD",
        entity_ref="source_records/rec_001",
        metadata={"line": 42},
        ledger_id="default",
    )

    dag.add_node(evidence_node)
    dag.add_node(record_node)

    edge = dag.add_edge(
        ledger_id="default",
        source_node_id="ev_001",
        target_node_id="rec_001",
        relationship="EXTRACTED_FROM",
    )

    assert edge.source_node_id == "ev_001"
    assert edge.target_node_id == "rec_001"
    assert edge.relationship == "EXTRACTED_FROM"


def test_self_edge_rejected(db_conn):
    dag = LineageDAG(db_conn)
    node = LineageNode(
        node_id="ev_self",
        node_type="EVIDENCE_BLOB",
        entity_ref="evidence/raw/test.pdf",
        ledger_id="default",
    )
    dag.add_node(node)

    with pytest.raises(LineageCycleError, match="[Ss]elf-edge"):
        dag.add_edge(
            ledger_id="default",
            source_node_id="ev_self",
            target_node_id="ev_self",
            relationship="EXTRACTED_FROM",
        )


def test_missing_node_for_edge_rejected(db_conn):
    dag = LineageDAG(db_conn)
    node = LineageNode(
        node_id="ev_existing",
        node_type="EVIDENCE_BLOB",
        entity_ref="evidence/raw/test.pdf",
        ledger_id="default",
    )
    dag.add_node(node)

    with pytest.raises((LineageNodeNotFoundError, sqlite3.IntegrityError)):
        dag.add_edge(
            ledger_id="default",
            source_node_id="ev_existing",
            target_node_id="non_existent",
            relationship="EXTRACTED_FROM",
        )


# ============================================================================
# 2. Insertion-Time Cycle Detection Tests
# ============================================================================


def test_cycle_detection_direct_reverse_rejected(db_conn):
    dag = LineageDAG(db_conn)

    n1 = LineageNode(node_id="n1", node_type="EVIDENCE_BLOB", entity_ref="ref1", ledger_id="default")
    n2 = LineageNode(node_id="n2", node_type="SOURCE_RECORD", entity_ref="ref2", ledger_id="default")
    dag.add_node(n1)
    dag.add_node(n2)

    dag.add_edge("default", "n1", "n2", "EXTRACTED_FROM")

    # Adding n2 -> n1 should create a cycle and be rejected
    with pytest.raises(LineageCycleError, match="[Cc]ycle"):
        dag.add_edge("default", "n2", "n1", "DERIVED_FROM")


def test_cycle_detection_multi_hop_rejected(db_conn):
    # Test A -> B -> C -> D -> A cycle detection
    dag = LineageDAG(db_conn)

    nodes = [
        LineageNode(node_id="A", node_type="EVIDENCE_BLOB", entity_ref="refA", ledger_id="default"),
        LineageNode(node_id="B", node_type="SOURCE_RECORD", entity_ref="refB", ledger_id="default"),
        LineageNode(node_id="C", node_type="STAGED_TX", entity_ref="refC", ledger_id="default"),
        LineageNode(node_id="D", node_type="POSTING", entity_ref="refD", ledger_id="default"),
    ]
    for n in nodes:
        dag.add_node(n)

    dag.add_edge("default", "A", "B", "EXTRACTED_FROM")
    dag.add_edge("default", "B", "C", "STAGED_FROM")
    dag.add_edge("default", "C", "D", "COMPILED_FROM")

    # Closing the loop D -> A should fail with LineageCycleError
    with pytest.raises(LineageCycleError, match="[Cc]ycle"):
        dag.add_edge("default", "D", "A", "DERIVED_FROM")


def test_cycle_detection_isolated_by_tenant(db_conn):
    dag = LineageDAG(db_conn)

    # Insert tenant_2 into ledgers
    db_conn.execute("INSERT INTO ledgers (ledger_id, name, base_currency) VALUES ('tenant_2', 'Tenant 2', 'USD')")
    db_conn.commit()

    # In default: X -> Y
    dag.add_node(LineageNode(node_id="X", node_type="EVIDENCE_BLOB", entity_ref="refX", ledger_id="default"))
    dag.add_node(LineageNode(node_id="Y", node_type="SOURCE_RECORD", entity_ref="refY", ledger_id="default"))
    dag.add_edge("default", "X", "Y", "EXTRACTED_FROM")

    # In tenant_2: Y -> X (Should be valid because they are separate tenants)
    dag.add_node(LineageNode(node_id="X", node_type="EVIDENCE_BLOB", entity_ref="refX", ledger_id="tenant_2"))
    dag.add_node(LineageNode(node_id="Y", node_type="SOURCE_RECORD", entity_ref="refY", ledger_id="tenant_2"))
    # This should succeed without cycle error
    dag.add_edge("tenant_2", "Y", "X", "EXTRACTED_FROM")


# ============================================================================
# 3. Upstream and Downstream Bi-Directional Recursive Traversal Tests
# ============================================================================


@pytest.fixture
def sample_lineage_graph(db_conn):
    dag = LineageDAG(db_conn)

    # Graph structure:
    #   ev1 (Evidence) -> rec1 (Record 1) -> tx1 (Staged Tx) -> post1 (Posting 1)
    #                                                       -> post2 (Posting 2)
    #   ev1 (Evidence) -> rec2 (Record 2) -> tx2 (Staged Tx) -> post3 (Posting 3)
    #   ev2 (Evidence 2) -> rec3 (Record 3) -> tx2

    nodes = [
        LineageNode(node_id="ev1", node_type="EVIDENCE_BLOB", entity_ref="evidence/doc1.pdf", ledger_id="default"),
        LineageNode(node_id="ev2", node_type="EVIDENCE_BLOB", entity_ref="evidence/doc2.pdf", ledger_id="default"),
        LineageNode(node_id="rec1", node_type="SOURCE_RECORD", entity_ref="rec_1", ledger_id="default"),
        LineageNode(node_id="rec2", node_type="SOURCE_RECORD", entity_ref="rec_2", ledger_id="default"),
        LineageNode(node_id="rec3", node_type="SOURCE_RECORD", entity_ref="rec_3", ledger_id="default"),
        LineageNode(node_id="tx1", node_type="STAGED_TX", entity_ref="tx_1", ledger_id="default"),
        LineageNode(node_id="tx2", node_type="STAGED_TX", entity_ref="tx_2", ledger_id="default"),
        LineageNode(node_id="post1", node_type="POSTING", entity_ref="post_1", ledger_id="default"),
        LineageNode(node_id="post2", node_type="POSTING", entity_ref="post_2", ledger_id="default"),
        LineageNode(node_id="post3", node_type="POSTING", entity_ref="post_3", ledger_id="default"),
    ]
    for n in nodes:
        dag.add_node(n)

    dag.add_edge("default", "ev1", "rec1", "EXTRACTED_FROM")
    dag.add_edge("default", "rec1", "tx1", "STAGED_FROM")
    dag.add_edge("default", "tx1", "post1", "COMPILED_FROM")
    dag.add_edge("default", "tx1", "post2", "COMPILED_FROM")

    dag.add_edge("default", "ev1", "rec2", "EXTRACTED_FROM")
    dag.add_edge("default", "rec2", "tx2", "STAGED_FROM")

    dag.add_edge("default", "ev2", "rec3", "EXTRACTED_FROM")
    dag.add_edge("default", "rec3", "tx2", "STAGED_FROM")
    dag.add_edge("default", "tx2", "post3", "COMPILED_FROM")

    return dag, LineageExplorer(db_conn)


def test_upstream_traversal_to_evidence(sample_lineage_graph):
    _, explorer = sample_lineage_graph

    # Upstream from post1 should reach tx1, rec1, ev1
    upstream = explorer.trace_upstream(ledger_id="default", start_node_id="post1")
    upstream_ids = {n.node_id for n in upstream.nodes}
    assert upstream_ids == {"post1", "tx1", "rec1", "ev1"}

    roots = explorer.get_root_ancestors(ledger_id="default", start_node_id="post1")
    assert {r.node_id for r in roots} == {"ev1"}

    # Upstream from post3 (multi-parent) should reach tx2, rec2, rec3, ev1, ev2
    upstream_post3 = explorer.trace_upstream(ledger_id="default", start_node_id="post3")
    upstream_post3_ids = {n.node_id for n in upstream_post3.nodes}
    assert upstream_post3_ids == {"post3", "tx2", "rec2", "rec3", "ev1", "ev2"}

    roots_post3 = explorer.get_root_ancestors(ledger_id="default", start_node_id="post3")
    assert {r.node_id for r in roots_post3} == {"ev1", "ev2"}


def test_downstream_blast_radius(sample_lineage_graph):
    _, explorer = sample_lineage_graph

    # Downstream from ev1 should reach rec1, rec2, tx1, tx2, post1, post2, post3
    downstream_ev1 = explorer.trace_downstream(ledger_id="default", start_node_id="ev1")
    downstream_ev1_ids = {n.node_id for n in downstream_ev1.nodes}
    assert downstream_ev1_ids == {"ev1", "rec1", "rec2", "tx1", "tx2", "post1", "post2", "post3"}

    leaves_ev1 = explorer.get_leaf_descendants(ledger_id="default", start_node_id="ev1")
    assert {l.node_id for l in leaves_ev1} == {"post1", "post2", "post3"}

    # Downstream from ev2 should reach rec3, tx2, post3
    downstream_ev2 = explorer.trace_downstream(ledger_id="default", start_node_id="ev2")
    assert {n.node_id for n in downstream_ev2.nodes} == {"ev2", "rec3", "tx2", "post3"}


def test_traversal_cross_tenant_isolation(sample_lineage_graph, db_conn):
    dag, explorer = sample_lineage_graph

    # Insert a node in tenant_b with identical id "post1"
    db_conn.execute("INSERT INTO ledgers (ledger_id, name, base_currency) VALUES ('tenant_b', 'Tenant B', 'USD')")
    db_conn.commit()

    dag.add_node(LineageNode(node_id="post1", node_type="POSTING", entity_ref="tenant_b_post_1", ledger_id="tenant_b"))

    # Upstream trace in tenant_b for post1 should only return itself (no links in tenant_b)
    upstream = explorer.trace_upstream(ledger_id="tenant_b", start_node_id="post1")
    assert len(upstream.nodes) == 1
    assert upstream.nodes[0].entity_ref == "tenant_b_post_1"


def test_traversal_depth_limit(db_conn):
    dag = LineageDAG(db_conn)
    explorer = LineageExplorer(db_conn)

    # Create a long chain of 60 nodes: N0 -> N1 -> ... -> N59
    for i in range(60):
        dag.add_node(LineageNode(node_id=f"N{i}", node_type="POSTING", entity_ref=f"ref{i}", ledger_id="default"))
        if i > 0:
            dag.add_edge("default", f"N{i-1}", f"N{i}", "DERIVED_FROM")

    # Trace downstream from N0 with max_depth=10
    bounded_trace = explorer.trace_downstream(ledger_id="default", start_node_id="N0", max_depth=10)
    assert len(bounded_trace.nodes) == 11  # N0 + 10 hops
    assert max(int(n.node_id[1:]) for n in bounded_trace.nodes) == 10


def test_lineage_models_invalid_inputs():
    with pytest.raises(ValueError):
        LineageNode(node_id="bad id with spaces", node_type="POSTING", entity_ref="ref1")
    with pytest.raises(ValueError):
        LineageNode(node_id="valid_id", node_type="INVALID_TYPE", entity_ref="ref1")  # type: ignore
    with pytest.raises(ValueError):
        LineageNode(node_id="valid_id", node_type="POSTING", entity_ref="")  # empty entity ref
    with pytest.raises(ValueError):
        LineageEdge(ledger_id="default", source_node_id="A", target_node_id="B", relationship="INVALID_REL")  # type: ignore


def test_lineage_trace_missing_start_node_raises(db_conn):
    explorer = LineageExplorer(db_conn)
    with pytest.raises(LineageNodeNotFoundError):
        explorer.trace_upstream(ledger_id="default", start_node_id="does_not_exist")
    with pytest.raises(LineageNodeNotFoundError):
        explorer.trace_downstream(ledger_id="default", start_node_id="does_not_exist")


def test_ast_no_beancount_import_in_lineage():
    import ast
    from pathlib import Path

    lineage_dir = Path(__file__).parent.parent / "src" / "ironledger" / "lineage"
    py_files = list(lineage_dir.glob("*.py"))
    assert len(py_files) >= 4

    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("beancount"), f"Forbidden import in {py_file.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("beancount"), f"Forbidden import from {py_file.name}"
