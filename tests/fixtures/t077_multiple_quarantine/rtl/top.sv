module t077_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] combined_o;
    logic [7:0] sibling_o;

    t077_combined_owner u_combined (
        .data_i(data_i),
        .data_o(combined_o)
    );
    t077_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = combined_o ^ sibling_o;
endmodule
