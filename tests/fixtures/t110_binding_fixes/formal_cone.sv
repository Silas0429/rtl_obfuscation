// T110 formal cone.  This file is deliberately self-contained and free of
// packed structs and interfaces: Yosys 0.53 aborts with an internal assert on
// any packed-struct member access and cannot parse a non-ANSI in-body
// `If.Mp x;` declaration, so those shapes live in design.sv and are covered by
// strict compilation and byte-identical restore instead.

// Instantiated four times below and again from design.sv, so elaboration
// produces many distinct target objects for each of these physical
// declarations.
module t110_leaf (
    input  logic x,
    input  logic y,
    output logic z
);
    logic mixed;
    assign mixed = x & y;
    assign z     = mixed ^ x;
endmodule

// The port declaration order a_first / b_second / c_third differs from the
// named connection order written at every instantiation of this module.  The
// trailing exclusive-or with a zero literal is a rename-stable anchor for the
// fixed functional negative.
module t110_reorder (
    input  logic a_first,
    input  logic b_second,
    input  logic c_third,
    output logic sum
);
    assign sum = ((a_first & b_second) ^ c_third) ^ 1'b0;
endmodule

module t110_formal_top (
    input  logic clk,
    input  logic in_a,
    input  logic in_b,
    output logic out_y
);
    logic z0;
    logic z1;
    logic z2;
    logic z3;
    logic sum;
    logic state;

    t110_leaf u_leaf0 (.x(in_a), .y(in_b), .z(z0));
    t110_leaf u_leaf1 (.x(in_b), .y(in_a), .z(z1));
    t110_leaf u_leaf2 (.x(in_a), .y(in_a), .z(z2));
    t110_leaf u_leaf3 (in_b, in_b, z3);

    t110_reorder u_reorder (
        .c_third(z0),
        .b_second(z1),
        .a_first(z2),
        .sum(sum)
    );

    always_ff @(posedge clk)
        state <= sum ^ z3;

    assign out_y = state;
endmodule
