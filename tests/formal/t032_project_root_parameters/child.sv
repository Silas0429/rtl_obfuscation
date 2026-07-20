module t032_child #(
    parameter integer WIDTH = 8,
    parameter integer DEPTH = 2
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    localparam integer SUM_W = WIDTH + DEPTH;
    logic [SUM_W-1:0] extended_data;

    always_comb begin
        extended_data = {{DEPTH{1'b0}}, data_i};
        data_o = extended_data[WIDTH-1:0];
    end
endmodule
