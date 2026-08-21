module t100_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] macro_o;
    logic [7:0] clean_o;

    t100_macro_owner u_macro (
        .data_i(data_i),
        .data_o(macro_o)
    );
    t100_clean u_clean (
        .data_i(data_i),
        .data_o(clean_o)
    );

    assign data_o = macro_o ^ clean_o;
endmodule
