// Gold input whose own design legitimately relies on an implicit net.
// The auditor must difference gate against gold, so this net must never be
// blamed on the rewrite.
module t112_implicit_leaf (input logic a, output logic b);
    assign b = a;
endmodule

module t112_implicit_top (input logic src, output logic dst);
    // `mid_wire` is never declared: SystemVerilog's default nettype makes it an
    // implicit wire here, in the ORIGINAL source.
    t112_implicit_leaf u_first  (.a(src),      .b(mid_wire));
    t112_implicit_leaf u_second (.a(mid_wire), .b(dst));
endmodule
