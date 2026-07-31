module t071_defparam_owner (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] defparam_out;

    t071_defparam_target u_target (
        .data_i(data_i),
        .data_o(defparam_out)
    );
    defparam u_target.WIDTH = 8'h3c;

    assign data_o = defparam_out;
endmodule
