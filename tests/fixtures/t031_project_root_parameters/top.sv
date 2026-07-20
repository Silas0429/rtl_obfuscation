`define T031_DECLARE_LOCALPARAM localparam int MACRO_LOCAL = DATA_WIDTH;

module parameter_top #(
    parameter int DATA_WIDTH = 16,
    parameter int LANES = 2,
    localparam int TOP_LOCAL = DATA_WIDTH + 1
) (
    input  logic [DATA_WIDTH-1:0] data_i,
    output logic [DATA_WIDTH-1:0] data_o
);
    localparam int PARTIAL_SUM_W = DATA_WIDTH + 8;
    localparam int DIV_CALC_CYCLES = 4;
    localparam int DIV_BIT_GROUPS = DATA_WIDTH / DIV_CALC_CYCLES;

    typedef struct packed {
        logic [DATA_WIDTH-1:0] payload;
        logic [PARTIAL_SUM_W-1:0] sum;
    } packet_t;

    packet_t packet;
    logic [DATA_WIDTH-1:0] signal_a;
    logic [DATA_WIDTH-1:0] child_o;

    bus_if #(.WIDTH(DATA_WIDTH)) bus_inst();
    parameter_child #(
        .WIDTH(DATA_WIDTH),
        .DEPTH(DIV_BIT_GROUPS)
    ) u_child (
        .data_i(data_i),
        .data_o(child_o)
    );

    `T031_DECLARE_LOCALPARAM

    always_comb begin
        signal_a = data_i;
        packet.payload = signal_a;
        packet.sum = '0;
        for (int idx = 0; idx < DATA_WIDTH; idx++) begin
            packet.sum = packet.sum + idx;
        end
        if (LANES > 1) begin
            data_o = signal_a;
        end
    end

    generate
        for (genvar lane = 0; lane < LANES; lane++) begin : gen_lane
            logic [DATA_WIDTH-1:0] lane_data;
            assign lane_data = data_i;
        end
    endgenerate
endmodule
