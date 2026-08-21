module t101_top (
    input  logic data_i,
    output logic data_o
);
    logic selector_o;
    logic macro_o;
    logic clean_o;

    t101_selector u_selector (
        .data_i(data_i),
        .data_o(selector_o)
    );
    t101_macro_owner u_macro (
        .data_i(data_i),
        .data_o(macro_o)
    );
    t101_clean u_clean (
        .data_i(data_i),
        .data_o(clean_o)
    );

    assign data_o = selector_o ^ macro_o ^ clean_o;
endmodule
