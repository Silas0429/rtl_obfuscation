`define SIGNAL_REFERENCE(name) name

module macro_reference;
    logic state;
    assign state = `SIGNAL_REFERENCE(state);
endmodule
