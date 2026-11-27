# French UI strings (control-centre)

Generated from `services/control-centre/src/control_centre/locales/fr.toml` by
`uv run control-centre fr-strings docs/fr-ui-strings.md`; CI fails if it is stale.

Every French string is **unverified, written by Claude Code**, unless marked
**provided by the project owner**. Policy wording never comes from these files: it comes
from the French catalog. Have a qualified translator review the unverified strings
before any use outside the demo.

247 strings: 3 provided by the project owner, 244 unverified.

| Key | French | English | Status |
|---|---|---|---|
| `action.accept` | Accepter | Accept | Unverified, written by Claude Code |
| `action.accept-with-remediation` | Accepter avec mesures correctives | Accept with remediation | Unverified, written by Claude Code |
| `action.accept-with-remediation.hint` | La constatation est exacte; ajoute un élément au plan d'action et une tâche de mesures correctives. | The finding is correct; adds a plan-of-action item and a remediation task. | Unverified, written by Claude Code |
| `action.accept.hint` | La constatation est exacte; rien d'autre à faire. | The finding is correct; nothing more to do. | Unverified, written by Claude Code |
| `action.override-verdict` | Remplacer le verdict | Override the verdict | Unverified, written by Claude Code |
| `action.override-verdict.hint` | Remplacez le verdict par le vôtre. | Replace the verdict with your own. | Unverified, written by Claude Code |
| `action.reject` | Rejeter | Reject | Unverified, written by Claude Code |
| `action.reject.hint` | La constatation est erronée ou ne s'applique pas. | The finding is wrong or does not apply. | Unverified, written by Claude Code |
| `action.request-more-evidence` | Demander d'autres preuves | Request more evidence | Unverified, written by Claude Code |
| `action.request-more-evidence.hint` | Envoie une demande de preuves au responsable du système; la constatation reste dans la file. | Sends an evidence request to the system owner; the finding stays in the queue. | Unverified, written by Claude Code |
| `banner.demo` | Démo seulement : aucune authentification. | Demo only: no authentication. | Unverified, written by Claude Code |
| `banner.detail` | Toute personne qui accède à cette page agit comme l'examinateur de démonstration. Ne l'exposez pas. | Anyone who can reach this page acts as the demo reviewer. Do not expose it. | Unverified, written by Claude Code |
| `choose.heading` | Choisissez votre langue | Choose your language | Unverified, written by Claude Code |
| `choose.intro` | Prototype pour examiner des systèmes d'IA au regard des règles de gouvernance. Un modèle ne fait que rédiger une ébauche; une personne décide. | Prototype for reviewing AI systems against governance rules. A model only drafts; a person decides. | Unverified, written by Claude Code |
| `decide.action` | Décision | Decision | Unverified, written by Claude Code |
| `decide.annotation` | Motif ou note | Reason or note | Unverified, written by Claude Code |
| `decide.annotation_hint` | Obligatoire pour rejeter, demander d'autres preuves ou remplacer le verdict. | Required to reject, request more evidence or override the verdict. | Unverified, written by Claude Code |
| `decide.choose` | Choisissez un verdict | Choose a verdict | Unverified, written by Claude Code |
| `decide.error_action` | Choisissez une décision. | Choose a decision. | Unverified, written by Claude Code |
| `decide.error_annotation` | Indiquez le motif de cette décision. | Give a reason for this decision. | Unverified, written by Claude Code |
| `decide.error_refused` | Le bureau d'examen a refusé la décision : {detail} | The review desk refused the decision: {detail} | Unverified, written by Claude Code |
| `decide.error_remediation` | Décrivez les mesures correctives et indiquez leur échéance. | Describe the remediation and give its due date. | Unverified, written by Claude Code |
| `decide.error_verdict` | Choisissez le nouveau verdict. | Choose the new verdict. | Unverified, written by Claude Code |
| `decide.errors` | La décision n'a pas été consignée : | The decision was not recorded: | Unverified, written by Claude Code |
| `decide.heading` | Votre décision | Your decision | Unverified, written by Claude Code |
| `decide.new_verdict` | Nouveau verdict | New verdict | Unverified, written by Claude Code |
| `decide.override` | Seulement pour remplacer le verdict | Only to override the verdict | Unverified, written by Claude Code |
| `decide.recorded` | Décision consignée comme enregistrement {seq} du registre des décisions. | Decision recorded as record {seq} of the decision log. | Unverified, written by Claude Code |
| `decide.remediation` | Seulement pour accepter avec mesures correctives | Only to accept with remediation | Unverified, written by Claude Code |
| `decide.remediation_description` | Mesures correctives à prendre | Remediation to do | Unverified, written by Claude Code |
| `decide.remediation_due` | Échéance des mesures correctives | Remediation due date | Unverified, written by Claude Code |
| `decide.see_log` | Voir le registre des décisions | See the decision log | Unverified, written by Claude Code |
| `decide.start` | Commencer l'examen | Start review | Unverified, written by Claude Code |
| `decide.start_hint` | Le début de l'examen enregistre l'heure sur le serveur. Le temps de décision est mesuré à partir de ce moment. | Starting the review records the time on the server. The time to decide is measured from here. | Unverified, written by Claude Code |
| `decide.submit` | Consigner la décision | Record decision | Unverified, written by Claude Code |
| `decide.timer` | Séance d'examen {session} commencée; le temps de décision est mesuré. | Review session {session} started; the time to decide is being measured. | Unverified, written by Claude Code |
| `effect.evidence_task` | Demande de preuves | Evidence request | Unverified, written by Claude Code |
| `effect.poam` | Plan d'action, version {version} | Plan of action version {version} | Unverified, written by Claude Code |
| `effect.remediation_task` | Tâche de mesures correctives | Remediation task | Unverified, written by Claude Code |
| `effect.work_note` | Note de travail | Work note | Unverified, written by Claude Code |
| `error.home` | Retour à l'aperçu de la démo | Back to the demo overview | Unverified, written by Claude Code |
| `error.service` | Le service {service} n'a pas pu traiter la demande. | The {service} service could not complete the request. | Unverified, written by Claude Code |
| `error.title` | Une erreur s'est produite | Something went wrong | Unverified, written by Claude Code |
| `error.unreachable` | injoignable | unreachable | Unverified, written by Claude Code |
| `finding.ai_note` | Un modèle d'IA ne fait que rédiger une ébauche; une personne décide. Cette constatation est provisoire jusqu'à ce que le moteur d'évaluation existe. | An AI model only drafts; a person decides. This finding is a placeholder until the assessment engine exists. | Unverified, written by Claude Code |
| `finding.back` | Retour à la file d'examen | Back to the review queue | Unverified, written by Claude Code |
| `finding.confidence` | Confiance | Confidence | Unverified, written by Claude Code |
| `finding.evidence` | Preuves attendues | Evidence expected | Unverified, written by Claude Code |
| `finding.history` | Décisions sur cette constatation | Decisions on this finding | Unverified, written by Claude Code |
| `finding.history_caption` | Chaque décision est un enregistrement du registre des décisions chaîné par hachage | Every decision is a record in the hash-chained decision log | Unverified, written by Claude Code |
| `finding.no_confidence` | Aucune (pas d'évaluation automatisée) | None (no automated assessment) | Unverified, written by Claude Code |
| `finding.no_history` | Aucune décision pour l'instant. | No decision yet. | Unverified, written by Claude Code |
| `finding.rationale` | Justification | Rationale | Unverified, written by Claude Code |
| `finding.state` | État | Status | Unverified, written by Claude Code |
| `finding.statement` | Exigence | Requirement | Unverified, written by Claude Code |
| `finding.title` | Constatation | Finding | Unverified, written by Claude Code |
| `finding.verdict` | Verdict | Verdict | Unverified, written by Claude Code |
| `flag.added` | Ajoutée | Added | Unverified, written by Claude Code |
| `flag.merge` | Fusionnée | Merged | Unverified, written by Claude Code |
| `flag.obligation-change` | Obligation modifiée | Obligation changed | Unverified, written by Claude Code |
| `flag.removed` | Supprimée | Removed | Unverified, written by Claude Code |
| `flag.renumbered` | Renumérotée | Renumbered | Unverified, written by Claude Code |
| `flag.split` | Scindée | Split | Unverified, written by Claude Code |
| `flag.text-changed` | Libellé modifié | Wording changed | Unverified, written by Claude Code |
| `flag.unchanged` | Inchangée | Unchanged | Unverified, written by Claude Code |
| `footer.notice` | Prototype par Envision Global Consultancy Services Inc. Ce n'est pas un site Web du gouvernement du Canada. | Prototype by Envision Global Consultancy Services Inc. Not a Government of Canada website. | Provided by the project owner |
| `gap.department` | ministère | department | Unverified, written by Claude Code |
| `gap.impact_level` | niveau d'incidence | impact level | Unverified, written by Claude Code |
| `gap.lifecycle` | cycle de vie | lifecycle | Unverified, written by Claude Code |
| `gap.missing` | Manquant : {field} | Missing: {field} | Unverified, written by Claude Code |
| `gap.owner` | responsable | owner | Unverified, written by Claude Code |
| `gap.owner_email` | courriel du responsable | owner email | Unverified, written by Claude Code |
| `gap.profiles` | profils | profiles | Unverified, written by Claude Code |
| `gap.tenant` | groupe responsable | responsible group | Unverified, written by Claude Code |
| `home.ai` | Aucun modèle d'IA n'est encore utilisé : les constatations sont provisoires jusqu'à ce que le moteur d'évaluation existe. | No AI model is used yet: findings are placeholders until the assessment engine exists. | Unverified, written by Claude Code |
| `home.impact` | voir les contrôles et les systèmes touchés par le changement, et l'effort d'examen | see which controls and systems the change affects, and the review effort | Unverified, written by Claude Code |
| `home.intro` | Suivez un changement de règle, du texte de la politique jusqu'à une décision humaine consignée, en cinq écrans. | Follow one rule change from the policy text to a recorded human decision, in five screens. | Unverified, written by Claude Code |
| `home.inventory` | voir les systèmes d'IA et les lacunes dans leurs dossiers | see the AI systems and the gaps in their records | Unverified, written by Claude Code |
| `home.log` | vérifier que le registre des décisions n'a pas été modifié | check that the decision log has not been altered | Unverified, written by Claude Code |
| `home.policy` | comparer deux versions d'une directive, disposition par disposition | compare two versions of a directive clause by clause | Unverified, written by Claude Code |
| `home.review` | examiner les constatations classées et consigner une décision | review the ranked findings and record a decision | Unverified, written by Claude Code |
| `home.title` | Aperçu de la démo | Demo overview | Unverified, written by Claude Code |
| `impact.as_of` | En date du | As of | Unverified, written by Claude Code |
| `impact.as_of_hint` | Les échéances sont calculées à partir de cette date. | Due dates are counted from this date. | Unverified, written by Claude Code |
| `impact.assigned_group` | Groupe affecté | Assignment group | Unverified, written by Claude Code |
| `impact.capacity` | Capacité (heures par semaine) | Capacity (hours per week) | Unverified, written by Claude Code |
| `impact.capacity_caption` | Effort par groupe responsable par rapport à la capacité hebdomadaire | Effort per responsible group against weekly capacity | Unverified, written by Claude Code |
| `impact.capacity_flag` | Capacité | Capacity | Unverified, written by Claude Code |
| `impact.catalog` | Catalogue de contrôles | Control catalog | Unverified, written by Claude Code |
| `impact.catalog_version` | Version du catalogue | Catalog version | Unverified, written by Claude Code |
| `impact.clauses` | Dispositions sources | Source clauses | Unverified, written by Claude Code |
| `impact.control` | Contrôle | Control | Unverified, written by Claude Code |
| `impact.controls` | Contrôles touchés | Affected controls | Unverified, written by Claude Code |
| `impact.controls_affected` | Contrôles touchés | Controls affected | Unverified, written by Claude Code |
| `impact.controls_caption` | Contrôles dont les dispositions sources ont changé | Controls whose source clauses changed | Unverified, written by Claude Code |
| `impact.due` | Échéance | Due date | Unverified, written by Claude Code |
| `impact.excluded` | Systèmes non touchés ({n}) | Systems not affected ({n}) | Unverified, written by Claude Code |
| `impact.forecast` | Prévision des heures d'examen | Reviewer-hours forecast | Unverified, written by Claude Code |
| `impact.forecast_total` | {findings} constatations × {minutes} minutes = {hours} heures d'examen. | {findings} findings × {minutes} minutes = {hours} reviewer hours. | Unverified, written by Claude Code |
| `impact.hours` | Heures | Hours | Unverified, written by Claude Code |
| `impact.intro` | Les contrôles touchés par le changement, les systèmes d'IA à réévaluer en premier, les tâches envoyées à ServiceNow et l'effort d'examen. | Which controls the change touches, which AI systems must be reassessed first, the tasks sent to ServiceNow and the review effort. | Unverified, written by Claude Code |
| `impact.level` | Niveau d'incidence | Impact level | Unverified, written by Claude Code |
| `impact.level_unknown` | Inconnu (classé IV) | Unknown (ranked as IV) | Unverified, written by Claude Code |
| `impact.lifecycle` | Cycle de vie | Lifecycle | Unverified, written by Claude Code |
| `impact.machine_text` | les détails générés sont en anglais | generated details are in English | Unverified, written by Claude Code |
| `impact.maintenance` | Éléments de mise à jour du recueil de règles ({n}) | Rulebook maintenance items ({n}) | Unverified, written by Claude Code |
| `impact.n_controls` | Contrôles touchés | Controls affected | Unverified, written by Claude Code |
| `impact.n_findings` | Constatations à examiner | Findings to review | Unverified, written by Claude Code |
| `impact.n_systems` | Systèmes touchés | Systems affected | Unverified, written by Claude Code |
| `impact.next` | Aller à la file d'examen | Go to the review queue | Unverified, written by Claude Code |
| `impact.not_in_servicenow` | Pas encore dans ServiceNow | Not yet in ServiceNow | Unverified, written by Claude Code |
| `impact.over_capacity` | Dépasse la capacité hebdomadaire : {weeks} semaines nécessaires | Over weekly capacity: {weeks} weeks needed | Unverified, written by Claude Code |
| `impact.priority` | Priorité | Priority | Unverified, written by Claude Code |
| `impact.rank` | Rang | Rank | Unverified, written by Claude Code |
| `impact.rate_placeholder` | Taux provisoire jusqu'à ce que {needed} décisions chronométrées existent ({samples} jusqu'à présent). | Placeholder rate until {needed} timed decisions exist ({samples} so far). | Unverified, written by Claude Code |
| `impact.report_id` | Rapport | Report | Unverified, written by Claude Code |
| `impact.servicenow` | Numéro ServiceNow | ServiceNow number | Unverified, written by Claude Code |
| `impact.servicenow_unavailable` | L'état dans ServiceNow n'est pas disponible pour le moment; les tâches ci-dessous sont celles que le carrefour créerait. | ServiceNow status is unavailable right now; the tasks below are what the hub would create. | Unverified, written by Claude Code |
| `impact.show` | Afficher l'incidence | Show impact | Unverified, written by Claude Code |
| `impact.system` | Système | System | Unverified, written by Claude Code |
| `impact.systems` | Systèmes à réévaluer, incidence la plus élevée en premier | Systems to reassess, highest impact first | Unverified, written by Claude Code |
| `impact.systems_caption` | Systèmes touchés classés par niveau d'incidence | Affected systems ranked by impact level | Unverified, written by Claude Code |
| `impact.task` | Tâche | Task | Unverified, written by Claude Code |
| `impact.tasks` | Tâches de réévaluation | Reassessment tasks | Unverified, written by Claude Code |
| `impact.tasks_caption` | Une tâche par système, créée dans ServiceNow | One task per system, created in ServiceNow | Unverified, written by Claude Code |
| `impact.tenant` | Groupe responsable | Responsible group | Unverified, written by Claude Code |
| `impact.title` | 2. Rapport d'incidence | 2. Impact report | Unverified, written by Claude Code |
| `impact.why` | Motif | Why | Unverified, written by Claude Code |
| `impact.within_capacity` | Dans les limites de la capacité hebdomadaire | Within weekly capacity | Unverified, written by Claude Code |
| `inventory.caption` | Systèmes d'IA et lacunes dans leurs dossiers | AI systems and the gaps in their records | Unverified, written by Claude Code |
| `inventory.complete` | Complet | Complete | Unverified, written by Claude Code |
| `inventory.gaps` | Lacunes | Data gaps | Unverified, written by Claude Code |
| `inventory.gaps_hint` | Les systèmes avec des lacunes sont présentés en premier. | Systems with gaps are listed first. | Unverified, written by Claude Code |
| `inventory.intro` | Les systèmes d'IA connus du carrefour, lus dans ServiceNow. Les champs manquants ne bloquent jamais une évaluation : le système est classé comme ayant une incidence inconnue et son responsable reçoit une tâche pour les remplir. | The AI systems the hub knows about, read from ServiceNow. Missing fields never block an assessment: the system is ranked as unknown impact and its owner gets a task to fill them in. | Unverified, written by Claude Code |
| `inventory.n_gaps` | Systèmes avec des lacunes | Systems with data gaps | Unverified, written by Claude Code |
| `inventory.n_systems` | Systèmes | Systems | Unverified, written by Claude Code |
| `inventory.owner` | Responsable | Owner | Unverified, written by Claude Code |
| `inventory.profiles` | Profils | Profiles | Unverified, written by Claude Code |
| `inventory.snapshot` | instantané {n} | snapshot {n} | Unverified, written by Claude Code |
| `inventory.source` | Source | Source | Unverified, written by Claude Code |
| `inventory.title` | 5. Inventaire des systèmes | 5. System inventory | Unverified, written by Claude Code |
| `label.placeholder` | VALEUR PROVISOIRE | PLACEHOLDER | Unverified, written by Claude Code |
| `lang.switch` | English | Français | Unverified, written by Claude Code |
| `lifecycle.development` | Développement | Development | Unverified, written by Claude Code |
| `lifecycle.pilot` | Projet pilote | Pilot | Unverified, written by Claude Code |
| `lifecycle.production` | Production | Production | Unverified, written by Claude Code |
| `lifecycle.retired` | Retiré | Retired | Unverified, written by Claude Code |
| `lifecycle.unknown` | Inconnu | Unknown | Unverified, written by Claude Code |
| `log.checkpoints` | Points de contrôle externes | External checkpoints | Unverified, written by Claude Code |
| `log.checkpoints_caption` | Dernier point de contrôle à chaque endroit | Latest checkpoint in each place | Unverified, written by Claude Code |
| `log.checkpoints_intro` | Après chaque tranche de {every} décision(s), le numéro et le hachage du dernier enregistrement sont aussi écrits hors de la base de données : dans un fichier de points de contrôle et dans une note de travail ServiceNow. La suppression des enregistrements les plus récents dans la base de données est donc quand même détectée. | After every {every} decision(s), the latest record number and hash are also written outside the database: to a checkpoint file and as a work note in ServiceNow. Deleting the newest records in the database is then still detected. | Unverified, written by Claude Code |
| `log.effects` | Suivi | Follow-up | Unverified, written by Claude Code |
| `log.finding` | Constatation | Finding | Unverified, written by Claude Code |
| `log.hashes` | Hachages | Hashes | Unverified, written by Claude Code |
| `log.intro` | Chaque décision humaine est un enregistrement. Chaque enregistrement contient le hachage du précédent; modifier, supprimer ou réordonner un enregistrement brise donc la chaîne. | Every human decision is one record. Each record holds the hash of the one before it, so changing, removing or reordering a record breaks the chain. | Unverified, written by Claude Code |
| `log.latest_hash` | Hachage | Hash | Unverified, written by Claude Code |
| `log.latest_seq` | Enregistrement | Record | Unverified, written by Claude Code |
| `log.not_verified` | Le registre a été modifié : | The log has been altered: | Unverified, written by Claude Code |
| `log.previous` | précédent : | previous: | Unverified, written by Claude Code |
| `log.records` | {n} enregistrements | {n} records | Unverified, written by Claude Code |
| `log.records_caption` | Enregistrements du registre des décisions | Decision log records | Unverified, written by Claude Code |
| `log.records_heading` | Enregistrements | Records | Unverified, written by Claude Code |
| `log.records_intro` | Les plus récents d'abord; {shown} sur {total} affichés. | Newest first; {shown} of {total} shown. | Unverified, written by Claude Code |
| `log.reviewer` | Examinateur | Reviewer | Unverified, written by Claude Code |
| `log.seq` | Enregistrement | Record | Unverified, written by Claude Code |
| `log.source` | Endroit | Where | Unverified, written by Claude Code |
| `log.source.database` | Base de données (dernier enregistrement) | Database (latest record) | Unverified, written by Claude Code |
| `log.source.file` | Fichier de points de contrôle | Checkpoint file | Unverified, written by Claude Code |
| `log.source.servicenow` | Notes de travail ServiceNow | ServiceNow work notes | Unverified, written by Claude Code |
| `log.state` | État | Status | Unverified, written by Claude Code |
| `log.state.ahead` | En avance de {n} sur la base de données : des enregistrements manquent | Ahead of the database by {n}: records are missing | Unverified, written by Claude Code |
| `log.state.behind` | En retard de {n} enregistrement(s) sur la base de données | {n} record(s) behind the database | Unverified, written by Claude Code |
| `log.state.in-step` | Concorde avec la base de données | Matches the database | Unverified, written by Claude Code |
| `log.state.none` | Aucun point de contrôle pour l'instant | No checkpoint yet | Unverified, written by Claude Code |
| `log.state.unavailable` | Injoignable pour le moment | Not reachable right now | Unverified, written by Claude Code |
| `log.this` | celui-ci : | this: | Unverified, written by Claude Code |
| `log.title` | 4. Registre des décisions | 4. Decision log | Unverified, written by Claude Code |
| `log.trust_legend` | Comparer aussi avec les points de contrôle conservés hors de la base de données | Also compare with the checkpoints kept outside the database | Unverified, written by Claude Code |
| `log.verified` | Le registre est intact. | The log is intact. | Unverified, written by Claude Code |
| `log.verified_detail` | {records} enregistrements vérifiés; {checkpoints} points de contrôle externes concordent. | {records} records checked; {checkpoints} external checkpoints match. | Unverified, written by Claude Code |
| `log.verify` | Vérifier le registre | Verify the log | Unverified, written by Claude Code |
| `log.verify_heading` | Vérifier le registre | Check the log | Unverified, written by Claude Code |
| `log.when` | Date | When | Unverified, written by Claude Code |
| `nav.impact` | Rapport d'incidence | Impact report | Unverified, written by Claude Code |
| `nav.inventory` | Inventaire des systèmes | System inventory | Unverified, written by Claude Code |
| `nav.label` | Écrans de la démo | Demo screens | Unverified, written by Claude Code |
| `nav.log` | Registre des décisions | Decision log | Unverified, written by Claude Code |
| `nav.policy` | Changement de politique | Policy change | Unverified, written by Claude Code |
| `nav.review` | File d'examen | Review queue | Unverified, written by Claude Code |
| `nav.skip` | Passer au contenu principal | Skip to main content | Unverified, written by Claude Code |
| `note.fictional` | Systèmes et responsables fictifs | Fictional systems and owners | Provided by the project owner |
| `note.label` | Remarque : | Note: | Unverified, written by Claude Code |
| `note.synthetic` | Données d'essai synthétiques, pas une politique réelle | Synthetic test data, not real policy | Provided by the project owner |
| `policy.changes` | Changements | Changes | Unverified, written by Claude Code |
| `policy.clauses` | {n} dispositions | {n} clauses | Unverified, written by Claude Code |
| `policy.compare` | Comparer | Compare | Unverified, written by Claude Code |
| `policy.from` | Version antérieure | Older version | Unverified, written by Claude Code |
| `policy.instrument` | Directive | Directive | Unverified, written by Claude Code |
| `policy.intro` | Choisissez deux versions d'une directive. Chaque disposition de l'ancienne version est jumelée à la nouvelle, même si elle a été renumérotée, scindée ou fusionnée. | Pick two versions of a directive. Each clause of the old version is matched to the new one, even when it was renumbered, split or merged. | Unverified, written by Claude Code |
| `policy.method` | Comment les dispositions sont jumelées | How clauses are matched | Unverified, written by Claude Code |
| `policy.new_clause` | Disposition en {version} | Clause in {version} | Unverified, written by Claude Code |
| `policy.next` | Voir l'incidence de ce changement | See the impact of this change | Unverified, written by Claude Code |
| `policy.no_sources` | Aucun document source n'est encore enregistré. | No source documents are stored yet. | Unverified, written by Claude Code |
| `policy.none` | (aucune) | (none) | Unverified, written by Claude Code |
| `policy.obligation` | Obligation : {before} → {after} | Obligation: {before} → {after} | Unverified, written by Claude Code |
| `policy.old_clause` | Disposition en {version} | Clause in {version} | Unverified, written by Claude Code |
| `policy.same_version` | Choisissez deux versions différentes. | Pick two different versions. | Unverified, written by Claude Code |
| `policy.similarity` | Similarité {score} | Similarity {score} | Unverified, written by Claude Code |
| `policy.summary` | Résumé des changements | Summary of changes | Unverified, written by Claude Code |
| `policy.table_caption` | Disposition par disposition, de {from} à {to} | Clause by clause, {from} to {to} | Unverified, written by Claude Code |
| `policy.thresholds` | Seuil de jumelage {threshold}; seuil de scission et de fusion {split}. | Pairing threshold {threshold}; split and merge threshold {split}. | Unverified, written by Claude Code |
| `policy.title` | 1. Changement de politique | 1. Policy change | Unverified, written by Claude Code |
| `policy.to` | Version plus récente | Newer version | Unverified, written by Claude Code |
| `reason.clause-added` | Disposition ajoutée | Clause added | Unverified, written by Claude Code |
| `reason.clause-changed` | Disposition modifiée | Clause changed | Unverified, written by Claude Code |
| `reason.clause-merged` | Dispositions fusionnées | Clauses merged | Unverified, written by Claude Code |
| `reason.clause-removed` | Disposition supprimée | Clause removed | Unverified, written by Claude Code |
| `reason.clause-split` | Disposition scindée | Clause split | Unverified, written by Claude Code |
| `reason.control-added` | Contrôle ajouté | Control added | Unverified, written by Claude Code |
| `reason.control-changed` | Contrôle modifié | Control changed | Unverified, written by Claude Code |
| `review.caption` | Constatations ouvertes, classées | Open findings, ranked | Unverified, written by Claude Code |
| `review.empty` | Aucune constatation n'attend de décision. | No findings are waiting for a decision. | Unverified, written by Claude Code |
| `review.intro` | Les constatations qui attendent une personne, les plus urgentes en premier. Ouvrez-en une, consultez les preuves et consignez une décision. | Findings waiting for a person, most urgent first. Open one, look at the evidence and record a decision. | Unverified, written by Claude Code |
| `review.ranking` | Comment la file est classée | How the queue is ranked | Unverified, written by Claude Code |
| `review.ranking_text` | Niveau d'incidence (inconnu d'abord, puis de IV à I), puis gravité du verdict, puis incertitude (aucune confiance ou confiance la plus faible d'abord), puis échéance. | Impact level (unknown first, then IV to I), then verdict severity, then uncertainty (no confidence or lowest confidence first), then due date. | Unverified, written by Claude Code |
| `review.title` | 3. File d'examen | 3. Review queue | Unverified, written by Claude Code |
| `review.total` | {n} constatations attendent une décision. | {n} findings waiting for a decision. | Unverified, written by Claude Code |
| `site.title` | Carrefour de gouvernance de l'IA (prototype) | AI Governance Hub (prototype) | Unverified, written by Claude Code |
| `state.accepted` | Acceptée | Accepted | Unverified, written by Claude Code |
| `state.accepted-with-remediation` | Acceptée avec mesures correctives | Accepted with remediation | Unverified, written by Claude Code |
| `state.awaiting-evidence` | En attente de preuves | Awaiting evidence | Unverified, written by Claude Code |
| `state.open` | Ouverte | Open | Unverified, written by Claude Code |
| `state.overridden` | Verdict remplacé | Verdict overridden | Unverified, written by Claude Code |
| `state.rejected` | Rejetée | Rejected | Unverified, written by Claude Code |
| `summary.added` | Ajoutées | Added | Unverified, written by Claude Code |
| `summary.merges` | Fusionnées | Merged | Unverified, written by Claude Code |
| `summary.obligation-change` | Obligation modifiée | Obligation changed | Unverified, written by Claude Code |
| `summary.removed` | Supprimées | Removed | Unverified, written by Claude Code |
| `summary.renumbered` | Renumérotées | Renumbered | Unverified, written by Claude Code |
| `summary.splits` | Scindées | Split | Unverified, written by Claude Code |
| `summary.text-changed` | Libellé modifié | Wording changed | Unverified, written by Claude Code |
| `summary.unchanged` | Inchangées | Unchanged | Unverified, written by Claude Code |
| `verdict.met` | Respecté | Met | Unverified, written by Claude Code |
| `verdict.not-applicable` | Sans objet | Not applicable | Unverified, written by Claude Code |
| `verdict.not-met` | Non respecté | Not met | Unverified, written by Claude Code |
| `verdict.partially-met` | Partiellement respecté | Partially met | Unverified, written by Claude Code |
| `verdict.unable-to-determine` | Impossible à déterminer | Unable to determine | Unverified, written by Claude Code |
