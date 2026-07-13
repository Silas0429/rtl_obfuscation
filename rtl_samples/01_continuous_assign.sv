// Sample 01: logic ports, an internal signal, and continuous assignment.
module sample01_continuous_assign (
    input  logic input_a,
    input  logic input_b,
    output logic output_y
);

    logic and_result;

    assign and_result = input_a & input_b;
    assign output_y = and_result;

endmodule
