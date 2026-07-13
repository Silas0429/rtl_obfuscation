module formal_variable_rename (
    input  logic       clock,
    input  logic       reset,
    input  logic       enable,
    output logic [3:0] count_value
);

    logic [3:0] Q7m2_xAa;

    always_ff @(posedge clock) begin
        if (reset) begin
            Q7m2_xAa <= '0;
        end else if (enable) begin
            Q7m2_xAa <= Q7m2_xAa + 2'd2;
        end
    end

    assign count_value = Q7m2_xAa;

endmodule
