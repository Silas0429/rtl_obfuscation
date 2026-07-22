module t038_child #(
    parameter int WIDTH = 4,
    localparam int EXTRA = WIDTH + WIDTH + 1
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    // T038 effective-line denominator fixture.

    logic [WIDTH-1:0] storage;
    assign storage = data_i;
    assign data_o = storage;

    genvar j;
    generate
        for (j = 0; j < WIDTH; j = j + 1) begin : g_first
            logic [j:0] lane_first;
            assign lane_first = '0;
        end
        for (j = 0; j < WIDTH; j = j + 1) begin : g_second
            logic [j:0] lane_second;
            assign lane_second = '0;
        end
    endgenerate
endmodule
