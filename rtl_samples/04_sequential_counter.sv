// Sample 04: typed parameter, always_ff, and synchronous reset.
module sample04_sequential_counter #(
    parameter int unsigned WIDTH = 8
) (
    input  logic             clock,
    input  logic             reset,
    input  logic             enable,
    output logic [WIDTH-1:0] count_value
);

    logic [WIDTH-1:0] count_register;

    always_ff @(posedge clock) begin
        if (reset) begin
            count_register <= '0;
        end else if (enable) begin
            count_register <= count_register + 1'b1;
        end
    end

    assign count_value = count_register;

endmodule
