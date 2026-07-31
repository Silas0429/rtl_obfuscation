module t069_sized_cast_shadow #(
    parameter int WIDTH = 3
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    if (1) begin : g_shadow
        localparam int WIDTH = 2;
        logic [WIDTH-1:0] shadow_value;

        always_comb begin
            shadow_value = WIDTH'(data_i);
        end
    end

    assign data_o = WIDTH'(data_i);
endmodule
