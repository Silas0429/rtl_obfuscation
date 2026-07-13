// Sample 03: always_comb, if/else, and procedural assignment.
module sample03_combinational_always (
    input  logic [3:0] input_a,
    input  logic [3:0] input_b,
    input  logic       select_b,
    output logic [3:0] output_y
);

    logic [3:0] selected_value;

    always_comb begin
        if (select_b) begin
            selected_value = input_b;
        end else begin
            selected_value = input_a;
        end
    end

    assign output_y = selected_value;

endmodule
