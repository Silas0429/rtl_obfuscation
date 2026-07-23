module leaf;
    logic secret;
    assign secret = 1'b0;
endmodule

module hierarchical;
    leaf u_leaf();
    logic sink;
    assign sink = u_leaf.secret;
endmodule
