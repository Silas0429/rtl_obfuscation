interface bus_if #(parameter int WIDTH = 8);
    logic [WIDTH-1:0] data;
    modport master(output data);
endinterface
