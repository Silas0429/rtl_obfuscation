module t018_child (
    t018_bus_if bus_inst
);
    assign bus_inst.valid = 1'b1;
    assign bus_inst.data = 8'hAA;
endmodule
