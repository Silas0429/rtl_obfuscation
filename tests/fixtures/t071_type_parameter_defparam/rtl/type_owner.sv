`ifdef T071_TYPED_VIEW
module t071_type_owner #(
    parameter type DATA_T = logic [7:0]
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    DATA_T type_hold;

    assign type_hold = data_i ^ 8'h0f;
    assign data_o = type_hold;
endmodule
`else
module t071_type_owner (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] type_hold;

    assign type_hold = data_i ^ 8'h0f;
    assign data_o = type_hold;
endmodule
`endif
