interface bus_if;
    logic valid;
    logic ready;
    modport master(input valid, output ready);
endinterface
