`include "macros.svh"

typedef struct packed {
    logic [3:0] field;
    logic       flag;
} payload_t;

module child (
    input  logic   clk,
    bus_if bus,
    input  payload_t payload,
    output logic   result
);
    logic internal_signal;
    payload_t explicit_payload;
    always_comb explicit_payload = payload_t'(payload);
    always_comb result = internal_signal ^ payload.flag ^ bus.valid;
endmodule

module macro_argument_owner (
    input  logic data_i,
    output logic data_o
);
    logic macro_argument_signal;
    `T108_ASSIGN(macro_argument_signal, data_i);
    assign data_o = macro_argument_signal;
endmodule

module macro_conflict_a (
    input  logic data_i,
    output logic data_o
);
    logic t108_shared_body;
    `T108_BODY_ASSIGN(data_i);
    assign data_o = t108_shared_body;
endmodule

module macro_conflict_b (
    input  logic data_i,
    output logic data_o
);
    logic t108_shared_body;
    `T108_BODY_ASSIGN(data_i);
    assign data_o = t108_shared_body;
endmodule

module macro_unique_body (
    input  logic data_i,
    output logic data_o
);
    logic t108_unique_body;
    `T108_UNIQUE_BODY(data_i);
    assign data_o = t108_unique_body;
endmodule

module type_cases (
    output logic result
);
    typedef struct packed {
        logic [1:0] field;
        logic       flag;
    } payload_t;
    parameter type payload_parameter_t = payload_t;
    payload_t local_payload;
    payload_parameter_t converted_payload;
    always_comb begin
        converted_payload = local_payload;
        result = converted_payload.flag;
    end
endmodule

module top (
    input logic clk,
    output logic result
);
    bus_if if0();
    bus_if if_arr[1:0]();
    bus_if if_matrix[1:0][1:0]();
    payload_t payload;
    logic macro_argument_result;
    logic macro_conflict_a_result;
    logic macro_conflict_b_result;
    logic macro_unique_result;
    logic type_result;
    logic child_result;
    child u_child (
        .clk(clk),
        .bus(if0),
        .payload(payload),
        .result(child_result)
    );
    macro_argument_owner u_macro_argument (
        .data_i(clk),
        .data_o(macro_argument_result)
    );
    macro_conflict_a u_macro_conflict_a (
        .data_i(clk),
        .data_o(macro_conflict_a_result)
    );
    macro_conflict_b u_macro_conflict_b (
        .data_i(clk),
        .data_o(macro_conflict_b_result)
    );
    macro_unique_body u_macro_unique_body (
        .data_i(clk),
        .data_o(macro_unique_result)
    );
    type_cases u_type_cases (.result(type_result));
    assign result = child_result ^ macro_argument_result ^ macro_conflict_a_result
        ^ macro_conflict_b_result ^ macro_unique_result ^ type_result;
endmodule
