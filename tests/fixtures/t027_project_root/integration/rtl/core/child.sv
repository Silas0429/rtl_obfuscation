module project_child (
    input  logic                    clk,
    input  logic                    reset_n,
    input  logic                    child_valid_i,
    input  logic [`T027_WIDTH-1:0]  child_data_i,
    output logic                    child_valid_o,
    output logic [`T027_WIDTH-1:0]  child_data_o
);
    packet_t child_packet;
    logic child_signal;

    always_comb begin
        child_packet.packet_valid = child_valid_i;
        child_packet.packet_payload = child_data_i;
        child_signal = child_packet.packet_valid;
    end

    project_leaf u_leaf (
        .clk          (clk),
        .reset_n      (reset_n),
        .leaf_valid_i (child_signal),
        .leaf_data_i  (child_packet.packet_payload),
        .leaf_valid_o (child_valid_o),
        .leaf_data_o  (child_data_o)
    );
endmodule
