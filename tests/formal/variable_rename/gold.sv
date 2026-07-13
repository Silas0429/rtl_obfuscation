module formal_variable_rename (
    input  logic       clock,
    input  logic       reset,
    input  logic       enable,
    output logic [3:0] count_value
);

    logic [3:0] count_register;

    always_ff @(posedge clock) begin
        if (reset) begin
            count_register <= '0;
        end else if (enable) begin
            count_register <= count_register + 1'b1;
        end
    end

    assign count_value = count_register;

endmodule
