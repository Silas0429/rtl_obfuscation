`include "declare.svh"

module macro_top(input logic value_i, output logic value_o);
    `T027_DECLARE_SIGNAL(macro_signal);
    assign macro_signal = value_i;
    assign value_o = macro_signal;
endmodule
