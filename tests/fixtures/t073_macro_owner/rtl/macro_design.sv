`define T073_DECLARE(name) logic name
`define T073_REFERENCE(name) name
`define T073_REGISTER(q, d, clk) always_ff @(posedge clk) q <= d
`define T073_ASSERT(clk, sig) always_ff @(posedge clk) assert (sig == sig)
`define T073_TARGET_TYPE t073_macro_target

module t073_macro_target (
    input  logic data_i,
    output logic data_o
);
    logic target_state;

    assign target_state = ~data_i;
    assign data_o = target_state;
endmodule

module t073_macro_owner (
    input  logic clk_i,
    input  logic data_i,
    output logic data_o
);
    `T073_DECLARE(macro_state);
    logic ref_state;
    logic reg_q;
    logic target_o;

    assign macro_state = data_i;
    assign ref_state = `T073_REFERENCE(data_i);
    `T073_REGISTER(reg_q, ref_state, clk_i);
    `T073_ASSERT(clk_i, reg_q);

    `T073_TARGET_TYPE u_target (
        .data_i(macro_state),
        .data_o(target_o)
    );

    assign data_o = reg_q ^ target_o;
endmodule

module t073_macro_statement_owner (
    input  logic clk_i,
    input  logic data_i,
    output logic data_o
);
    logic reg_q;

    `T073_REGISTER(reg_q, data_i, clk_i);
    `T073_ASSERT(clk_i, reg_q);

    assign data_o = reg_q;
endmodule
