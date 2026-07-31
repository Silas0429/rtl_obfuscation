module t069_sized_cast_top (
    input  logic [3:0] data_i,
    output logic [3:0] data_o
);
    logic [3:0] child_o;
    logic [2:0] shadow_o;

    t069_sized_cast_child #(
        .WIDTH(4),
        .RESET_VALUE(1)
    ) u_child (
        .data_i(data_i),
        .data_o(child_o)
    );

    t069_sized_cast_shadow #(
        .WIDTH(3)
    ) u_shadow (
        .data_i(data_i[2:0]),
        .data_o(shadow_o)
    );

    assign data_o = child_o ^ {1'b0, shadow_o};
endmodule
