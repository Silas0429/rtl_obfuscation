`include "macro_interface.svh"

interface macro_if;
    logic value;
    `T108_DECLARE_MODPORT(macro_mp);
endinterface

module macro_interface_top (
    output logic result
);
    `T108_DECLARE_IF_INSTANCE(if0);
    `T108_DECLARE_IF_ARRAY(if_array);
    always_comb result = if0.value ^ if_array[0].value;
endmodule
