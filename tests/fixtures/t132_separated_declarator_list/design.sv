module t132_multi_declarators (
    input  logic [3:0] in_i,
    output logic [3:0] out_o
);
    logic [3:0] first, second;
    wire  [3:0] third = second, fourth = third;
    logic [3:0] fifth, folded;

    assign first = in_i;
    assign second = first ^ 4'h3;
    assign fifth = fourth ^ 4'h1;
    assign folded = fifth;
    assign out_o = folded;
endmodule
