module t070_keyword_cast_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] child_o;

    t070_keyword_cast_child u_child (
        .data_i(data_i),
        .data_o(child_o)
    );

    assign data_o = child_o ^ 8'ha5;
endmodule
