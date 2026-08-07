module t075_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] protected_o;
    logic [7:0] sibling_o;

    t075_defparam_owner u_protected (
        .data_i(data_i),
        .data_o(protected_o)
    );
    t075_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = protected_o ^ sibling_o;
endmodule
