module t073_top (
    input  logic clk_i,
    input  logic data_i,
    output logic data_o
);
    logic macro_o;
    logic sibling_o;
    logic statement_o;

    t073_macro_owner u_macro (
        .clk_i(clk_i),
        .data_i(data_i),
        .data_o(macro_o)
    );
    t073_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );
    t073_macro_statement_owner u_statement (
        .clk_i(clk_i),
        .data_i(data_i),
        .data_o(statement_o)
    );

    assign data_o = macro_o ^ sibling_o ^ statement_o;
endmodule
