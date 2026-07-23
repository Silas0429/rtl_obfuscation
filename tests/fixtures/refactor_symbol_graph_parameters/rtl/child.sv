module parameter_child #(
    parameter int WIDTH = 2,
    parameter int DEPTH = 2,
    localparam int HEADER_LOCAL = WIDTH + 1
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    localparam int BODY_LOCAL = WIDTH + DEPTH + HEADER_LOCAL;
    logic [WIDTH-1:0] storage [0:DEPTH-1];
    logic [BODY_LOCAL-1:0] expanded;

    if (WIDTH > 1) begin : g_enabled
        logic [HEADER_LOCAL-1:0] generated;
    end

    for (genvar lane = 0; lane < DEPTH; lane++) begin : g_lane
        logic [WIDTH+lane-1:0] lane_data;
    end

    assign storage[0] = data_i;
    assign expanded = '0;
    assign data_o = storage[0];
endmodule
