module t131_shadowed (
    input  logic clk_i,
    input  logic data_i,
    output logic data_o
);
    logic state;

    function automatic logic invert(input logic value);
        logic state;
        state = ~value;
        invert = state;
    endfunction

    always_ff @(posedge clk_i)
        state <= invert(data_i);

    assign data_o = state;
endmodule
