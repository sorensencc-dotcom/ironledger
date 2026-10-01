-- Migration 0022: persist partial shipment line selections on split proposals
ALTER TABLE split_proposals ADD COLUMN selected_line_indices TEXT;
ALTER TABLE split_proposals ADD COLUMN allocated_tax_minor INTEGER;
ALTER TABLE split_proposals ADD COLUMN allocated_shipping_minor INTEGER;
ALTER TABLE split_proposals ADD COLUMN allocated_discount_minor INTEGER;