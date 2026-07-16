module abi_top (
    input abi_packet_t packet_i,
    abi_if.sink bus,
    output logic result_o
);
    assign result_o = packet_i.abi_field & bus.abi_signal;
endmodule
