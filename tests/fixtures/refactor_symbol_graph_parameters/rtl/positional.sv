module positional_child #(
    parameter int WIDTH = 2
);
endmodule

module positional_top;
    positional_child #(4) u_child();
endmodule
