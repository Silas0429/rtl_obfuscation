module t071_top (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] type_o;
    logic [7:0] defparam_o;
    logic [7:0] sibling_o;

    t071_type_owner u_type (
        .data_i(data_i),
        .data_o(type_o)
    );
    t071_defparam_owner u_defparam (
        .data_i(data_i),
        .data_o(defparam_o)
    );
    t071_sibling u_sibling (
        .data_i(data_i),
        .data_o(sibling_o)
    );

    assign data_o = type_o ^ defparam_o ^ sibling_o;
endmodule
