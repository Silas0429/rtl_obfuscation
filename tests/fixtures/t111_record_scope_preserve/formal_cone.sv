// T111 formal cone.  This file is deliberately free of packed structs and
// interfaces: Yosys 0.53 aborts with an internal assert on any packed-struct
// member access, so those shapes live in design.sv and are covered by strict
// compilation and byte-identical restore instead.  t111_top instantiates this
// cone, so every declaration below is also inside the design-level top closure.

module t111_cone_leaf (
    input  logic p,
    input  logic q,
    output logic r
);
    logic blend;
    assign blend = p & q;
    assign r     = blend ^ p;
endmodule

module t111_cone_mix (
    input  logic m_one,
    input  logic m_two,
    output logic m_out
);
    // The trailing exclusive-or with a zero literal is the rename-stable anchor
    // for the fixed functional negative: it is the only zero literal written in
    // this cone, and renaming never rewrites a literal.
    assign m_out = (m_one & m_two) ^ 1'b0;
endmodule

module t111_formal_top (
    input  logic clk,
    input  logic in_a,
    input  logic in_b,
    output logic out_y
);
    logic r0;
    logic r1;
    logic mixed;
    logic state;

    t111_cone_leaf u_leaf0 (.p(in_a), .q(in_b), .r(r0));
    t111_cone_leaf u_leaf1 (.p(in_b), .q(in_a), .r(r1));
    t111_cone_mix  u_mix    (.m_one(r0), .m_two(r1), .m_out(mixed));

    always_ff @(posedge clk)
        state <= mixed ^ r0;

    assign out_y = state;
endmodule
