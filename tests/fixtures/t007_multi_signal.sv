// T007 fixture: multiple internal variable and net signal forms.
module t007_multi_signal (
    input  logic input_a,
    input  logic input_b,
    output logic output_y
);

    logic logic_value;
    reg   legacy_reg;
    wire  wire_value;
    tri   tri_value;

    assign wire_value = input_a & input_b;
    assign tri_value = wire_value;

    always_comb begin
        logic_value = tri_value;
        legacy_reg = logic_value;
    end

    assign output_y = legacy_reg;

endmodule
