module defparam_child #(
    parameter int WIDTH = 2
);
endmodule

module defparam_top;
    defparam_child u_child();
    defparam u_child.WIDTH = 4;
endmodule
