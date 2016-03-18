sbgnviz_indra_test
==================

Installation / Setup
--------------------

1. Install python packages::

    pip install -r requirements.txt

   Note that if you have problems installing cython or jnius-indra, which are
   dependencies of indra, you can ignore them as this demo doesn't need that
   functionality.

2. Verify that INDRA-SBGN assembly works::

    python indra_sbgn_assembler.py

   You should see some generated SBGN-ML output.

Running the agent
-----------------

The agent explicitly connects to localhost:3000 at the moment, but it should
be trivial to modify the code to change that if necessary. The room ID is
provided as a command-line argument, though::

    python agent.py <room_id>

The client will report on the users currently in the room and echo any chat
messages it sees. There will also be some debug prints from indra which we've
neglected to remove and can be ignored.

Interacting with the agent via the Editor
-----------------------------------------

Once the agent, "INDRA", has connected to the Editor, submit text
to be assembled by writing it in the chat with the prefix "indra:". For example::

    indra: EGFR binds EGF. EGFR bound to EGF phosphorylates itself at Y1068.

The agent will acknowledge that it has accepted text for processing, and then
make another announcement when the processing is complete.

Note that the parser used behind the scenes is slow. Even five or six simple sentences
could take upwards of one minute to process. Also keep in mind that the canvas
is cleared before each new model is loaded, i.e. it does not add nodes
incrementally to an existing map.
