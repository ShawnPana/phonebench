// pbcontacts — seed/remove/count contacts inside a simulator, the sanctioned
// way (CNContactStore), so the UI, index, and daemons all agree.
//   pbcontacts add "Carol" "Phonebench" "555-0142"
//   pbcontacts remove "Carol" "Phonebench"
//   pbcontacts count
@import Contacts;
@import EventKit;
@import Foundation;

// Reminders have no discoverable store file on disk; EventKit is the
// sanctioned channel (TCC-granted via `simctl privacy grant reminders`).
static int reminders_cmd(NSString *cmd, int argc, char **argv) {
    EKEventStore *ek = [EKEventStore new];
    dispatch_semaphore_t sem = dispatch_semaphore_create(0);
    __block NSArray<EKReminder *> *found = @[];
    NSPredicate *pred = [ek predicateForRemindersInCalendars:nil];
    [ek fetchRemindersMatchingPredicate:pred completion:^(NSArray *rs) {
        found = rs ?: @[];
        dispatch_semaphore_signal(sem);
    }];
    dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 15 * NSEC_PER_SEC));
    NSString *needle = argc > 2 ? [@(argv[2]) lowercaseString] : nil;
    NSMutableArray *hits = [NSMutableArray new];
    for (EKReminder *r in found)
        if (!needle || [[r.title lowercaseString] containsString:needle])
            [hits addObject:r];
    if ([cmd isEqualToString:@"rcount"]) {
        NSMutableArray *titles = [NSMutableArray new];
        for (EKReminder *r in hits) [titles addObject:r.title ?: @""];
        NSData *j = [NSJSONSerialization dataWithJSONObject:titles options:0 error:nil];
        printf("{\"ok\": true, \"count\": %lu, \"titles\": %s}\n",
               (unsigned long)hits.count,
               [[[NSString alloc] initWithData:j encoding:4] UTF8String]);
        return 0;
    }
    if ([cmd isEqualToString:@"rremove"]) {
        NSError *err = nil;
        for (EKReminder *r in hits)
            [ek removeReminder:r commit:NO error:&err];
        [ek commit:&err];
        printf("{\"ok\": %s, \"removed\": %lu}\n", err ? "false" : "true",
               (unsigned long)hits.count);
        return 0;
    }
    printf("{\"ok\": false, \"error\": \"unknown reminders cmd\"}\n");
    return 1;
}

int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *cmd = argc > 1 ? @(argv[1]) : @"count";
        if ([cmd hasPrefix:@"r"] && ![cmd isEqualToString:@"remove"])
            return reminders_cmd(cmd, argc, argv);
        CNContactStore *store = [CNContactStore new];
        NSError *err = nil;
        if ([cmd isEqualToString:@"add"]) {
            CNMutableContact *c = [CNMutableContact new];
            c.givenName = @(argv[2]); c.familyName = @(argv[3]);
            c.phoneNumbers = @[[CNLabeledValue labeledValueWithLabel:CNLabelPhoneNumberMobile
                value:[CNPhoneNumber phoneNumberWithStringValue:@(argv[4])]]];
            CNSaveRequest *req = [CNSaveRequest new];
            [req addContact:c toContainerWithIdentifier:nil];
            BOOL ok = [store executeSaveRequest:req error:&err];
            printf("{\"ok\": %s%s%s}\n", ok ? "true" : "false",
                   err ? ", \"error\": \"" : "", err ? [[err localizedDescription] UTF8String] : "");
            return ok ? 0 : 1;
        }
        // enumerate + filter by exact given/family name: the name predicate
        // misses vCard-imported contacts, enumeration never does
        NSString *g = argc > 2 ? @(argv[2]) : nil, *f = argc > 3 ? @(argv[3]) : nil;
        NSArray *keys = @[CNContactGivenNameKey, CNContactFamilyNameKey, CNContactPhoneNumbersKey];
        NSMutableArray *found = [NSMutableArray new];
        CNContactFetchRequest *fr = [[CNContactFetchRequest alloc] initWithKeysToFetch:keys];
        [store enumerateContactsWithFetchRequest:fr error:&err
            usingBlock:^(CNContact *c, BOOL *stop) {
                if (!g || ([c.givenName isEqualToString:g] &&
                           (!f || [c.familyName isEqualToString:f])))
                    [found addObject:c];
            }];
        if ([cmd isEqualToString:@"remove"]) {
            CNSaveRequest *req = [CNSaveRequest new];
            for (CNContact *c in found) [req deleteContact:[c mutableCopy]];
            BOOL ok = [store executeSaveRequest:req error:&err];
            printf("{\"ok\": %s, \"removed\": %lu}\n", ok || found.count == 0 ? "true" : "false",
                   (unsigned long)found.count);
            return 0;
        }
        printf("{\"ok\": true, \"count\": %lu}\n", (unsigned long)found.count);
        return 0;
    }
}
