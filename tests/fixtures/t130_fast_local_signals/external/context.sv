package t130_context_pkg;
    typedef struct packed {
        logic       state;
        logic [3:0] payload;
    } packet_t;
    logic global_state;
endpackage

interface t130_context_if;
    logic state;
    logic ready;
    modport client (output state, input ready);
endinterface

module t130_vendor_cell (
    input  logic data_i,
    output logic data_o
);
    logic state;
    assign state = data_i;
    assign data_o = state;
endmodule
