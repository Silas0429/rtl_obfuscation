module t106_stress (
    input logic [1:0] data_i,
    output logic [1:0] data_o
);
    t106_left_pkg::shared_t left_value;
    t106_right_pkg::shared_t right_value;
    logic [1:0] left_o;
    logic [1:0] right_o;

    always_comb begin
        left_value = data_i;
        right_value = data_i;
    end

    t106_left u_left (
        .typed_i(left_value),
        .out_o(left_o)
    );
    t106_right u_right (
        .typed_i(right_value),
        .out_o(right_o)
    );

    assign data_o = left_o ^ right_o;
endmodule
