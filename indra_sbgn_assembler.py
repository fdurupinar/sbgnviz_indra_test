import sys
import itertools
import copy
import collections
import lxml.builder
import lxml.etree
from indra.trips import trips_api
from indra import statements as ist


abbrevs = {
    'PhosphorylationSerine': 'S',
    'PhosphorylationThreonine': 'T',
    'PhosphorylationTyrosine': 'Y',
    'Phosphorylation': 'phospho',
    'Ubiquitination': 'ub',
    'Farnesylation': 'farnesyl',
    'Hydroxylation': 'hydroxyl',
    'Acetylation': 'acetyl',
    'Sumoylation': 'sumo',
    'Glycosylation': 'glycosyl',
    'Methylation': 'methyl',
    'Modification': 'mod',
}

states = {
    'PhosphorylationSerine': ['u', 'p'],
    'PhosphorylationThreonine': ['u', 'p'],
    'PhosphorylationTyrosine': ['u', 'p'],
    'Phosphorylation': ['u', 'p'],
    'Ubiquitination': ['n', 'y'],
    'Farnesylation': ['n', 'y'],
    'Hydroxylation': ['n', 'y'],
    'Acetylation': ['n', 'y'],
    'Sumoylation': ['n', 'y'],
    'Glycosylation': ['n', 'y'],
    'Methylation': ['n', 'y'],
    'Modification': ['n', 'y'],
}


def site_name(stmt):
    """Return all site names for a modification-type statement."""
    names = []
    if isinstance(stmt.mod, (list, tuple)):
        for m, mp in zip(stmt.mod, stmt.mod_pos):
            mod = abbrevs[m]
            mod_pos = mp if mp is not None else ''
            names.append('%s%s' % (mod, mod_pos))
    else:
        mod = abbrevs[stmt.mod]
        mod_pos = stmt.mod_pos if stmt.mod_pos is not None else ''
        names.append('%s%s' % (mod, mod_pos))

    return names


def get_activating_mods(agent, agent_set):
    act_mods = agent_set[agent.name].activating_mods
    if not act_mods:
        act_mods = [{}]
    return act_mods

# PySB model elements ##################################################

def get_agent_rule_str(agent):
    rule_str_list = [agent.name]
    if agent.mods:
        for m, mp in zip(agent.mods, agent.mod_sites):
            mstr = abbrevs[m]
            mpstr = '' if mp is None else str(mp)
            rule_str_list.append('%s%s' % (mstr, mpstr))
    if agent.bound_conditions:
        for b in agent.bound_conditions:
            if b.is_bound:
                rule_str_list.append(b.agent.name)
            else:
                rule_str_list.append('n' + b.agent.name)
    rule_str = '_'.join(rule_str_list)
    return rule_str

def add_rule_to_model(model, rule):
    try:
        model.add_component(rule)
    # If this rule is already in the model, issue a warning and continue
    except ComponentDuplicateNameError:
        msg = "Rule %s already in model! Skipping." % rule.name
        warnings.warn(msg)


def get_create_parameter(model, name, value, unique=True):
    """Return parameter with given name, creating it if needed.

    If unique is false and the parameter exists, the value is not changed; if
    it does not exist, it will be created. If unique is true then upon conflict
    a number is added to the end of the parameter name.
    """

    parameter = model.parameters.get(name)

    if not unique and parameter is not None:
        return parameter

    if unique:
        pnum = 1
        while True:
            pname = name + '_%d' % pnum
            if model.parameters.get(pname) is None:
                break
            pnum += 1
    else:
        pname = name

    parameter = Parameter(pname, value)
    model.add_component(parameter)
    return parameter


def get_complex_pattern(model, agent, agent_set, extra_fields=None):
    """Constructs a PySB ComplexPattern from an Agent"""

    monomer = model.monomers[agent.name]
    pattern = {}

    if extra_fields is not None:
        for k, v in extra_fields.iteritems():
            pattern[k] = v

    for bc in agent.bound_conditions:
        # Here we make the assumption that the binding site
        # is simply named after the binding partner
        if bc.is_bound:
            pattern[get_binding_site_name(bc.agent.name)] = ANY
        else:
            pattern[get_binding_site_name(bc.agent.name)] = None

    # Add the pattern for the modifications of the agent
    # TODO: This is specific to phosphorylation but we should be
    # able to support other types as well
    for m, mp in zip(agent.mods, agent.mod_sites):
        mod = abbrevs[m]
        mod_pos = mp if mp is not None else ''
        mod_site = ('%s%s' % (mod, mod_pos))
        pattern[mod_site] = 'p'

    complex_pattern = monomer(**pattern)
    return complex_pattern


def add_default_initial_conditions(model):
    # Iterate over all monomers
    for m in model.monomers:
        set_base_initial_condition(model, m, 100.0)


def set_base_initial_condition(model, monomer, value):
    # Build up monomer pattern dict
    sites_dict = {}
    for site in monomer.sites:
        if site in monomer.site_states:
            sites_dict[site] = monomer.site_states[site][0]
        else:
            sites_dict[site] = None
    mp = monomer(**sites_dict)
    pname = monomer.name + '_0'
    try:
        p = model.parameters[pname]
        p.value = value
    except KeyError:
        p = Parameter(pname, value)
        model.add_component(p)
        model.initial(mp, p)


def get_annotation(component, db_name, db_ref):
    '''
    Construct Annotation following format guidelines
    given at http://identifiers.org/.
    '''
    url = 'http://identifiers.org/'
    subj = component
    if db_name == 'UP':
        obj = url + 'uniprot/%s' % db_ref
        pred = 'is'
    elif db_name == 'HGNC':
        obj = url + 'hgnc/HGNC:%s' % db_ref
        pred = 'is'
    elif db_name == 'XFAM' and db_ref.startswith('PF'):
        obj = url + 'pfam/%s' % db_ref
        pred = 'is'
    elif db_name == 'IP':
        obj = url + 'interpro/%s' % db_ref
        pred = 'is'
    elif db_name == 'CHEBI':
        obj = url + 'chebi/CHEBI:%s' % db_ref
        pred = 'is'
    else:
        return None
    return Annotation(subj, obj, pred)

# PysbAssembler #######################################################

class UnknownPolicyError(Exception):
    pass


class PysbAssembler(object):
    def __init__(self, policies=None):
        self.statements = []
        self.agent_set = None
        self.model = None
        if policies is None:
            self.policies = {'other': 'default'}
        elif isinstance(policies, basestring):
            self.policies = {'other': policies}
        else:
            self.policies = {'other': 'default'}
            self.policies.update(policies)

    def statement_exists(self, stmt):
        for s in self.statements:
            if stmt.matches(s):
                return True
        return False

    def add_statements(self, stmts):
        for stmt in stmts:
            if not self.statement_exists(stmt):
                self.statements.append(stmt)

    def dispatch(self, stmt, stage, *args):
        class_name = stmt.__class__.__name__
        try:
            policy = self.policies[class_name]
        except KeyError:
            policy = self.policies['other']
        func_name = '%s_%s_%s' % (class_name.lower(), stage, policy)
        func = globals().get(func_name)
        if func is None:
            raise UnknownPolicyError('%s function %s not defined' %
                                     (stage, func_name))
        return func(stmt, *args)

    def monomers(self):
        """Calls the appropriate monomers method based on policies."""
        for stmt in self.statements:
            self.dispatch(stmt, 'monomers', self.agent_set)

    def assemble(self):
        for stmt in self.statements:
            self.dispatch(stmt, 'assemble', self.model, self.agent_set)

    def make_model(self, initial_conditions=True):
        self.model = Model()
        self.agent_set = BaseAgentSet()
        # Collect information about the monomers/self.agent_set from the
        # statements
        self.monomers()
        # Add the monomers to the model based on our BaseAgentSet
        for agent_name, agent in self.agent_set.iteritems():
            m = Monomer(agent_name, agent.sites, agent.site_states)
            self.model.add_component(m)
            for db_name, db_ref in agent.db_refs.iteritems():
                a = get_annotation(m, db_name, db_ref)
                if a is not None:
                    self.model.add_annotation(a)
        # Iterate over the statements to generate rules
        self.assemble()
        # Add initial conditions
        if initial_conditions:
            add_default_initial_conditions(self.model)
        return self.model

    def print_model(self, fname='pysb_model.py'):
        if self.model is not None:
            with open(fname, 'wt') as fh:
                fh.write(pysb.export.export(self.model, 'pysb_flat'))

    def print_rst(self, fname='pysb_model.rst', module_name='pysb_module'):
        if self.model is not None:
            with open(fname, 'wt') as fh:
                fh.write('.. _%s:\n\n' % module_name)
                fh.write('Module\n======\n\n')
                fh.write('INDRA-assembled model\n---------------------\n\n')
                fh.write('::\n\n')
                model_str = pysb.export.export(self.model, 'pysb_flat')
                model_str = '\t' + model_str.replace('\n', '\n\t')
                fh.write(model_str)


class SBGNAssembler(object):

    def __init__(self, policies=None):
        self.statements = []
        self.agent_set = None

    def statement_exists(self, stmt):
        for s in self.statements:
            if stmt.matches(s):
                return True
        return False

    def add_statements(self, stmts):
        for stmt in stmts:
            if not self.statement_exists(stmt):
                self.statements.append(stmt)

    def make_sbgn(self):

        def make_id(_counter=[0]):
            id_ = 'id_%d' % _counter[0]
            _counter[0] += 1
            return id_

        def class_(name):
            return {'class': name}

        def glyph_for_monomer(agent, in_complex=False):
            if in_complex:
                agent_id = make_id()
            else:
                agent_id = agent_ids[agent.matches_key()]
            glyph = E.glyph(
                E.label(text=agent.name),
                E.bbox(x='0', y='0', w='120', h='60'),
                class_('macromolecule'), id=agent_id,
                )
            for st in sbgn_states_for_agent(agent):
                glyph.append(
                    E.glyph(
                        E.state(**st._asdict()),
                        E.bbox(x='1', y='1', w='70', h='30'),
                        class_('state variable'), id=make_id(),
                        )
                    )
            return glyph

        def glyph_for_complex(agent):
            glyph = E.glyph(
                E.bbox(x='0', y='0', w='120', h='60'),
                class_('complex'), id=agent_ids[agent.matches_key()],
                )
            for component in complex_components(agent):
               glyph.append(glyph_for_monomer(component, in_complex=True))
            return glyph

        E = lxml.builder.ElementMaker(nsmap={None: 'http://sbgn.org/libsbgn/pd/0.1'})
        root = E.sbgn()
        map = E.map()
        root.append(map)
        base = agents_for_statements(self.statements)
        transformed = transformed_agents(self.statements)
        agents = distinct_agents(base + transformed)
        agent_ids = {a.matches_key(): make_id() for a in agents}
        for a in agents:
            if not a.bound_conditions:
                glyph = glyph_for_monomer(a)
            else:
                glyph = glyph_for_complex(a)
            map.append(glyph)
        for s in self.statements:
            if isinstance(s, ist.Modification):
                class_name = 'process'
                consumed = [s.sub]
            elif isinstance(s, ist.Complex):
                class_name = 'association'
                consumed = s.members
            else:
                print >>sys.stderr, "WARNING: skipping %s" % type(s)
                continue
            produced = [statement_product(s)]
            pg_id = make_id()
            process_glyph = E.glyph(E.bbox(x='0', y='0', w='20', h='20'),
                                    class_(class_name), id=pg_id)
            map.append(process_glyph)
            for c in consumed:
                map.append(
                    E.arc(class_('consumption'),
                          source=agent_ids[c.matches_key()],
                          target=pg_id,
                          id=make_id(),
                          )
                    )
            for p in produced:
                map.append(
                    E.arc(class_('production'),
                          source=pg_id,
                          target=agent_ids[p.matches_key()],
                          id=make_id(),
                          )
                    )
            if isinstance(s, ist.Modification):
                map.append(
                    E.arc(class_('catalysis'),
                          source=agent_ids[s.enz.matches_key()],
                          target=pg_id,
                          id=make_id(),
                          )
                    )
        return lxml.etree.tostring(root, pretty_print=True)

SBGNState = collections.namedtuple('SBGNState', 'variable value')

def sbgn_states_for_agent(agent):
    agent_states = []
    for m, mp in zip(agent.mods, agent.mod_sites):
        mod = abbrevs[m]
        mod_pos = mp if mp is not None else ''
        variable = '%s%s' % (mod, mod_pos)
        value = states[m][1].upper()
        agent_states.append(SBGNState(variable, value))
    return agent_states

def agents_for_statements(statements):
    return [a for stmt in statements for a in stmt.agent_list()]

def transformed_agents(statements):
    agents = [statement_product(s) for s in statements]
    # Following filter not needed once all statement types are implemented.
    return [a for a in agents if a is not None]

def statement_product(stmt):
    if isinstance(stmt, ist.Modification):
        product = copy.deepcopy(stmt.sub)
        product.mods.append(stmt.mod)
        product.mod_sites.append(stmt.mod_pos)
    elif isinstance(stmt, ist.Complex):
        product = copy.deepcopy(stmt.members[0])
        for member in stmt.members[1:]:
            bc = ist.BoundCondition(member, True)
            product.bound_conditions.append(bc)
    elif isinstance(stmt, ist.ActivityModification):
        print >>sys.stderr, "WARNING: skipping ActivityModification"
        product = None
    else:
        raise RuntimeError("%s not implemented yet" % type(stmt))
    return product

def distinct_agents(agents):
    agents = sorted(agents, key=ist.Agent.matches_key)
    gb = itertools.groupby(agents, ist.Agent.matches_key)
    distinct = [next(g[1]) for g in gb]
    return distinct

def complex_components(agent):
    agent_copy = copy.copy(agent)
    agent_copy.bound_conditions = []
    agents = [agent_copy]
    for bc in agent.bound_conditions:
        agents += complex_components(bc.agent)
    return agents


if __name__ == '__main__':
    tp = trips_api.process_xml(open('trips_output.xml').read())
    sa = SBGNAssembler()
    sa.add_statements(tp.statements)
    sbgn_output = sa.make_sbgn()
    print sbgn_output
    with open('output.sbgn', 'w') as f:
        f.write(sbgn_output)
    print
    print ">> SBGN content written to output.sbgn <<"
