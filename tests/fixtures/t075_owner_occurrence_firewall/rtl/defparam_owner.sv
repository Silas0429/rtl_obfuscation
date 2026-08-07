module t075_defparam_owner (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] configured_o;
    logic [7:0] child_o;

    t075_parameter_target u_target (
        .data_i(data_i),
        .data_o(configured_o)
    );
    defparam u_target.WIDTH = 8;

    t075_child u_child (
        .data_i(configured_o),
        .data_o(child_o)
    );

    assign data_o = child_o;
endmodule
