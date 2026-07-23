module uninstantiated_child #(parameter int P = 0);
endmodule

module uninstantiated_top #(parameter bit ENABLE = 1'b1);
    generate
        if (ENABLE) begin : active
            uninstantiated_child #(.P(1)) u_active();
        end
        else begin : inactive
            uninstantiated_child #(.Q(1)) u_inactive();
        end
    endgenerate
endmodule
