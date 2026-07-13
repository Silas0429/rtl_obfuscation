// Sample 05: typed localparams, always_comb, and a case statement.
module sample05_case_statement (
    input  logic [1:0] operation,
    input  logic [7:0] operand_a,
    input  logic [7:0] operand_b,
    output logic [7:0] result
);

    localparam logic [1:0] OP_ADD = 2'b00;
    localparam logic [1:0] OP_SUB = 2'b01;
    localparam logic [1:0] OP_AND = 2'b10;
    localparam logic [1:0] OP_OR  = 2'b11;

    logic [7:0] result_next;

    always_comb begin
        case (operation)
            OP_ADD:  result_next = operand_a + operand_b;
            OP_SUB:  result_next = operand_a - operand_b;
            OP_AND:  result_next = operand_a & operand_b;
            OP_OR:   result_next = operand_a | operand_b;
            default: result_next = '0;
        endcase
    end

    assign result = result_next;

endmodule
