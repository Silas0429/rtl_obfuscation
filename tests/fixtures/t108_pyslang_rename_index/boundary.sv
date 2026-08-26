`include "boundary_macros.svh"

typedef struct packed {
    logic ordinary_field;
} ordinary_struct_t;

typedef struct packed {
    `T108_FIELD(boundary_field);
} boundary_macro_struct_t;

module boundary_top (
    input logic clk,
    output logic result
);
    ordinary_struct_t ordinary_value;
    boundary_macro_struct_t value;
    always_comb result = value.boundary_field ^ ordinary_value.ordinary_field ^ clk;
endmodule
