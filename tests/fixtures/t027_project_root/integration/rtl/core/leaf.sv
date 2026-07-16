module project_leaf (
    input  logic                    clk,
    input  logic                    reset_n,
    input  logic                    leaf_valid_i,
    input  logic [`T027_WIDTH-1:0]  leaf_data_i,
    output logic                    leaf_valid_o,
    output logic [`T027_WIDTH-1:0]  leaf_data_o
);
    packet_t leaf_packet;
    logic leaf_signal;

    always_ff @(posedge clk) begin
        if (!reset_n) begin
            leaf_packet <= '0;
            leaf_signal <= 1'b0;
        end else begin
            leaf_packet.packet_valid <= leaf_valid_i;
            leaf_packet.packet_payload <= leaf_data_i;
            leaf_signal <= leaf_valid_i;
        end
    end

    assign leaf_valid_o = leaf_signal & leaf_packet.packet_valid;
    assign leaf_data_o = leaf_packet.packet_payload;
endmodule
