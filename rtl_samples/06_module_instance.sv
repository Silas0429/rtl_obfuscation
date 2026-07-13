// Sample 06: child module, named port connections, and module instance.
module sample06_inverter_cell (
    input  logic cell_input,
    output logic cell_output
);

    logic inverted_value;

    assign inverted_value = ~cell_input;
    assign cell_output = inverted_value;

endmodule

module sample06_module_instance (
    input  logic top_input,
    output logic top_output
);

    logic instance_result;

    sample06_inverter_cell inverter_instance (
        .cell_input  (top_input),
        .cell_output (instance_result)
    );

    assign top_output = instance_result;

endmodule
