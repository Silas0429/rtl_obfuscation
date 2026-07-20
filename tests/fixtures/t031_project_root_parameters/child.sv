module parameter_child #(
    parameter int WIDTH = 8,
    parameter int DEPTH = 2
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    localparam int CHILD_SUM_W = WIDTH + DEPTH;
    logic [WIDTH-1:0] child_data;
    logic [CHILD_SUM_W-1:0] child_sum;

    always_comb begin
        child_data = data_i;
        child_sum = '0;
        for (int idx = 0; idx < DEPTH; idx++) begin
            child_sum = child_sum + idx;
        end
        data_o = child_data;
    end
endmodule

module unreachable_parameter_decoy #(
    parameter int WIDTH = 99
) (
    input logic [WIDTH-1:0] data_i
);
    localparam int DECOY_LOCAL = WIDTH + 1;
    logic [DECOY_LOCAL-1:0] decoy_data;
    assign decoy_data = '0;
endmodule
