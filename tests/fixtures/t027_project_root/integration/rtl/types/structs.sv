`include "common.svh"

typedef struct packed {
    logic packet_valid;
    logic [`T027_WIDTH-1:0] packet_payload;
} packet_t;
