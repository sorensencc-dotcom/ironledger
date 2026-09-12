import React, { useEffect, useRef } from "react";
import * as d3 from "d3";
import {
  sankey,
  sankeyLinkHorizontal,
  SankeyNode,
  SankeyLink,
} from "d3-sankey";
import type { SankeyFlowRow } from "../../types";

export type { SankeyFlowRow };

interface NodeExtra {
  id: string;
  name: string;
}
interface LinkExtra {
  value: number;
}

type SNode = SankeyNode<NodeExtra, LinkExtra>;
type SLink = SankeyLink<NodeExtra, LinkExtra>;

export const CashFlowSankey: React.FC<{
  flows: SankeyFlowRow[];
  width?: number;
  height?: number;
}> = ({ flows, width = 900, height = 450 }) => {
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (!svgRef.current || flows.length === 0) return;

    // Filter positive flows strictly
    const validFlows = flows.filter((f) => f.amount_minor_units > 0);
    if (validFlows.length === 0) return;

    const nodeIds = Array.from(
      new Set(validFlows.flatMap((d) => [d.source_node, d.target_node]))
    );
    const nodeMap = new Map(nodeIds.map((id, index) => [id, index]));

    const graphNodes: NodeExtra[] = nodeIds.map((id) => ({ id, name: id }));
    const graphLinks = validFlows.map((f) => ({
      source: nodeMap.get(f.source_node)!,
      target: nodeMap.get(f.target_node)!,
      value: Math.max(0.01, f.amount_minor_units / 100), // Converted strictly at presentation boundary
    }));

    const layout = sankey<NodeExtra, LinkExtra>()
      .nodeWidth(18)
      .nodePadding(14)
      .extent([
        [10, 10],
        [width - 10, height - 10],
      ]);

    try {
      const { nodes, links } = layout({
        nodes: graphNodes.map((d) => ({ ...d })),
        links: graphLinks.map((d) => ({ ...d })),
      });

      const svg = d3.select(svgRef.current);
      svg.selectAll("*").remove();

      // Render flow links
      svg
        .append("g")
        .attr("fill", "none")
        .attr("stroke-opacity", 0.35)
        .selectAll<SVGPathElement, SLink>("path")
        .data(links)
        .join("path")
        .attr("d", sankeyLinkHorizontal())
        .attr("stroke", "#8B3A1A")
        .attr("stroke-width", (d: SLink) => Math.max(1, d.width ?? 0));

      // Render node blocks
      svg
        .append("g")
        .selectAll<SVGRectElement, SNode>("rect")
        .data(nodes)
        .join("rect")
        .attr("x", (d: SNode) => d.x0 ?? 0)
        .attr("y", (d: SNode) => d.y0 ?? 0)
        .attr("height", (d: SNode) => Math.max(2, (d.y1 ?? 0) - (d.y0 ?? 0)))
        .attr("width", (d: SNode) => (d.x1 ?? 0) - (d.x0 ?? 0))
        .attr("fill", (d: SNode) =>
          d.name.startsWith("Income")
            ? "#5a9e6f"
            : d.name.startsWith("Expenses")
            ? "#b8412f"
            : d.name === "Operating:GrossFlow"
            ? "#B8922A"
            : "#C4501A"
        )
        .attr("rx", 0);

      // Node labels
      svg
        .append("g")
        .selectAll<SVGTextElement, SNode>("text")
        .data(nodes)
        .join("text")
        .attr("x", (d: SNode) =>
          (d.x0 ?? 0) < width / 2 ? (d.x1 ?? 0) + 6 : (d.x0 ?? 0) - 6
        )
        .attr("y", (d: SNode) => ((d.y1 ?? 0) + (d.y0 ?? 0)) / 2)
        .attr("dy", "0.35em")
        .attr("text-anchor", (d: SNode) =>
          (d.x0 ?? 0) < width / 2 ? "start" : "end"
        )
        .attr("class", "text-[11px] font-mono fill-[#e8dfd1]")
        .text((d: SNode) => {
          const shortName = d.name.split(":").pop() || d.name;
          const formattedVal = (d.value ?? 0).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          });
          return `${shortName} ($${formattedVal})`;
        });
    } catch {
      // Gracefully handle layout calculation edge cases
    }
  }, [flows, width, height]);

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      className="overflow-visible bg-[#1a1410] p-2 rounded-none border border-[#2c2420]"
    />
  );
};
